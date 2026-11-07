import streamlit as st

st.set_page_config(page_title="MatchMind AI", page_icon="⚽", layout="centered")

st.title("⚽ MatchMind AI")
st.caption("منصة تحليل المباريات والفرق - النسخة التفاعلية")

st.divider()

st.header("🔍 طلب تقرير تحليل جديد")

# مدخلات المستخدم
col1, col2 = st.columns(2)
with col1:
    team_a = st.text_input("اسم الفريق الأول (أو المنافس)", "الأهلي")
with col2:
    team_b = st.text_input("اسم الفريق الثاني", "الزمالك")

report_type = st.selectbox(
    "اختر نوع التقرير المطلوبة",
    ["تحليل نقط القوة والضعف", "التشكيل الخطة المتوقعة", "إحصائيات الأهداف والهجمات"]
)

if st.button("🚀 إنشاء التقرير الآن", type="primary"):
    st.success(f"جاري إنشاء تقرير ({report_type}) لمباراة **{team_a} vs {team_b}**...")
    
    # عرض نتائج تجريبية
    st.subheader("📊 ملخص التقرير المبدئي")
    st.info(f"تم تحليل بيانات مباراة {team_a} ضد {team_b} بنجاح.")
    
    st.metric(label="نسبة الاستحواذ المتوقعة", value="54%", delta="2%")
    st.metric(label="معدل الخطورة الهجومية", value="7.8/10")

st.divider()
st.caption("MatchMind AI © جميع الحقوق محفوظة")
