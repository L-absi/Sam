const admin = require('firebase-admin');

// يقرأ بيانات الاعتماد من متغير البيئة (GitHub Actions) أو من الملف محليًا
const serviceAccount = process.env.FIREBASE_CREDENTIALS
  ? JSON.parse(process.env.FIREBASE_CREDENTIALS)
  : require('./firebase-service-account.json');

admin.initializeApp({
  credential: admin.credential.cert(serviceAccount),
});

const db = admin.firestore();

/** تحويل معرف مثل general_surgery إلى "General Surgery" */
function readableId(value) {
  return value
    .replace(/_/g, ' ')
    .split(' ')
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

async function buildReferenceIndex() {
  console.log('🚀 Starting reference index build…');

  const questionsSnapshot = await db.collectionGroup('questions').get();
  console.log(`📄 Found ${questionsSnapshot.size} questions.`);

  const index = new Map(); // key: bookName

  questionsSnapshot.forEach((doc) => {
    const data = doc.data();
    const bookName =
      data.source?.bookName || data.questionData?.source?.bookName;
    if (!bookName) return;

    const trimmedBook = bookName.trim();
    if (!trimmedBook) return;

    const pathParts = doc.ref.path.split('/');
    if (pathParts.length < 6) return;
    const specialtyId = pathParts[1];
    const subjectId = pathParts[3];

    const title = readableId(
      subjectId.replace(new RegExp(`^${specialtyId}_`), '')
    );
    const specialtyTitle = readableId(specialtyId);

    if (!index.has(trimmedBook)) {
      index.set(trimmedBook, {
        bookName: trimmedBook,
        questionCount: 0,
        topics: new Map(),
      });
    }
    const entry = index.get(trimmedBook);
    entry.questionCount++;

    const topicKey = `${specialtyId}/${subjectId}`;
    if (!entry.topics.has(topicKey)) {
      entry.topics.set(topicKey, {
        specialtyId,
        subjectId,
        title,
        specialtyTitle,
        questionCount: 0,
      });
    }
    entry.topics.get(topicKey).questionCount++;
  });

  // نحذف المستندات القديمة ثم نكتب الجديدة بدفعات
  const existing = await db.collection('reference_index').get();
  const deleteBatch = db.batch();
  existing.forEach((d) => deleteBatch.delete(d.ref));
  if (!existing.empty) {
    await deleteBatch.commit();
    console.log(`🗑️ Cleared ${existing.size} old index documents.`);
  }

  let referenceCount = 0;
  let batch = db.batch();
  let batchCount = 0;

  for (const [, entry] of index) {
    const topicsArray = Array.from(entry.topics.values()).sort((a, b) => {
      if (a.specialtyTitle !== b.specialtyTitle)
        return a.specialtyTitle.localeCompare(b.specialtyTitle);
      return a.title.localeCompare(b.title);
    });

    const docRef = db.collection('reference_index').doc(); // auto ID
    batch.set(docRef, {
      bookName: entry.bookName,
      questionCount: entry.questionCount,
      topicCount: topicsArray.length,
      topics: topicsArray,
      updatedAt: admin.firestore.FieldValue.serverTimestamp(),
    });
    referenceCount++;
    batchCount++;

    if (batchCount === 400) {
      await batch.commit();
      batch = db.batch();
      batchCount = 0;
    }
  }

  if (batchCount > 0) await batch.commit();

  console.log(
    `✅ Index build complete: ${referenceCount} references written to 'reference_index'.`
  );
}

buildReferenceIndex().catch((err) => {
  console.error('❌ Failed:', err);
  process.exit(1);
});
