const admin = require('firebase-admin');

// 1. تحميل ملف حساب الخدمة وتهيئة التطبيق

// يقرأ بيانات الاعتماد من متغير البيئة الذي يوفره GitHub Actions
const serviceAccount = JSON.parse(process.env.FIREBASE_CREDENTIALS);

admin.initializeApp({
  credential: admin.credential.cert(serviceAccount)
});

const db = admin.firestore();

async function buildReferenceIndex() {
  console.log('🚀 بدء بناء فهرس المراجع...');

  // 2. جلب جميع الأسئلة من كل التخصصات والمواضيع باستخدام collectionGroup
  const questionsSnapshot = await db.collectionGroup('questions').get();
  console.log(`📄 تم العثور على ${questionsSnapshot.size} سؤالاً.`);

  const index = new Map(); // المفتاح: bookName

  // 3. المرور على كل سؤال وتجميع البيانات
  questionsSnapshot.forEach(doc => {
    const data = doc.data();
    const bookName = data.source?.bookName || data.questionData?.source?.bookName;
    if (!bookName) return; // تخطي الأسئلة التي لا تحتوي على اسم مرجع

    // استخراج معرفات التخصص والموضوع من مسار المستند
    const pathParts = doc.ref.path.split('/');
    const specialtyId = pathParts[1];
    const subjectId = pathParts[3];

    // إذا كان المرجع غير موجود في الذاكرة، قم بإنشاء إدخال جديد له
    if (!index.has(bookName)) {
      index.set(bookName, {
        bookName: bookName,
        questionCount: 0,
        topics: new Map(), // المفتاح: specialtyId/subjectId
      });
    }
    const entry = index.get(bookName);
    entry.questionCount++;

    // تجميع الإحصائيات لكل موضوع داخل المرجع
    const topicKey = `${specialtyId}/${subjectId}`;
    if (!entry.topics.has(topicKey)) {
      entry.topics.set(topicKey, {
        specialtyId: specialtyId,
        subjectId: subjectId,
        questionCount: 0,
      });
    }
    entry.topics.get(topicKey).questionCount++;
  });

  // 4. تحويل البيانات المجمعة إلى الشكل النهائي والكتابة إلى Firestore
  const batch = db.batch();
  let referenceCount = 0;

  for (const [bookName, entry] of index) {
    const topicsArray = Array.from(entry.topics.values());
    const docRef = db.collection('reference_index').doc(bookName); // اسم المستند هو اسم المرجع

    batch.set(docRef, {
      bookName: bookName,
      questionCount: entry.questionCount,
      topicCount: topicsArray.length,
      topics: topicsArray,
      updatedAt: admin.firestore.FieldValue.serverTimestamp(),
    });
    referenceCount++;
  }

  // 5. تنفيذ جميع عمليات الكتابة دفعة واحدة
  await batch.commit();
  console.log(`✅ تم بناء الفهرس بنجاح! تمت كتابة ${referenceCount} مرجعاً إلى مجموعة 'reference_index'.`);
}

buildReferenceIndex().catch(console.error);
